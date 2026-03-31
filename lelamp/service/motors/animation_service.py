import os
import csv
import time
import logging
import threading
from typing import Any, Dict, List, Optional
from lelamp.follower import LeLampFollowerConfig, LeLampFollower

logger = logging.getLogger(__name__)

# Default interpolation duration for move_to (seconds)
DEFAULT_MOVE_DURATION = 2.0

# Startup position for base_pitch and elbow_pitch only.
# Other servos (base_yaw, wrist_roll, wrist_pitch) are left released.
STARTUP_POSITION = {
    "base_pitch.pos": -30.0,
    "elbow_pitch.pos": 57.0,
}

# Duration for the startup move (seconds)
STARTUP_MOVE_DURATION = 5.0


def _motor_positions_from_bus(robot: LeLampFollower) -> Dict[str, float]:
    """Read Present_Position only — same numeric scale as CSV, no camera/LED path.

    get_observation() also reads cameras; async_read can block or stall on device.
    If sync_read hangs, the animation thread stops (symptom: HTTP 200 but no motion).
    """
    t0 = time.perf_counter()
    raw = robot.bus.sync_read("Present_Position")
    dt = time.perf_counter() - t0
    if dt > 0.75:
        logger.warning("slow sync_read Present_Position: %.2fs (serial/USB may be stalling)", dt)
    return {f"{motor}.pos": float(val) for motor, val in raw.items()}


class AnimationService:
    def __init__(self, port: str, lamp_id: str, fps: int = 30, duration: float = 5.0, idle_recording: str = "idle"):
        self.port = port
        self.lamp_id = lamp_id
        self.fps = fps
        self.duration = duration
        self.idle_recording = idle_recording
        self.robot_config = LeLampFollowerConfig(port=port, id=lamp_id)
        self.robot: LeLampFollower = None
        self.recordings_dir = os.path.join(os.path.dirname(__file__), "..", "..", "recordings")

        # State management
        self._recording_cache: Dict[str, List[Dict[str, float]]] = {}
        self._current_state: Optional[Dict[str, float]] = None
        self._current_recording: Optional[str] = None
        self._current_frame_index: int = 0
        self._current_actions: List[Dict[str, float]] = []
        self._interpolation_frames: int = 0
        self._interpolation_target: Optional[Dict[str, float]] = None

        # Music groove: loop while music is playing
        self._music_playing = False
        self._music_recording = "music_groove"

        # Custom event handling
        self._running = threading.Event()
        self._event_queue = []
        self._event_lock = threading.Lock()
        self._event_thread: Optional[threading.Thread] = None

        # Serial bus lock — all bus access (read/write/ping) must hold this lock
        self.bus_lock = threading.RLock()

        # Freeze flag — when set, _continue_playback() skips servo writes so camera can capture a stable frame
        self._frozen = threading.Event()

    # P gain — match upstream default (16 for all). Higher values cause jerky motion.
    _SERVO_PGAIN = {1: 16, 2: 16, 3: 16, 4: 16, 5: 16}

    def _configure_servos_raw(self):
        """Configure servos directly via scservo_sdk, bypassing lerobot.

        lerobot's bus.write() requires a fully successful connect() handshake.
        When servos are offline, connect() fails and bus.write() raises
        DeviceNotConnectedError. This method writes directly to the serial bus
        to configure whichever servos are actually online.
        """
        with self.bus_lock:
            ph = self.robot.bus.port_handler
            pk = self.robot.bus.packet_handler
            from scservo_sdk import COMM_SUCCESS
            for motor_name, motor_obj in self.robot.bus.motors.items():
                sid = motor_obj.id
                pgain = self._SERVO_PGAIN.get(sid, 32)
                # Ping first
                _, result, _ = pk.ping(ph, sid)
                if result != COMM_SUCCESS:
                    logger.warning(f"{motor_name} (ID {sid}): offline, skipping")
                    continue
                pk.write1ByteTxRx(ph, sid, 40, 0)   # Torque_Enable = 0
                pk.write1ByteTxRx(ph, sid, 33, 0)   # Operating_Mode = position
                pk.write1ByteTxRx(ph, sid, 21, pgain)  # P_Coefficient
                pk.write1ByteTxRx(ph, sid, 23, 0)   # I_Coefficient
                pk.write1ByteTxRx(ph, sid, 22, 32)  # D_Coefficient
                pk.write1ByteTxRx(ph, sid, 40, 1)   # Torque_Enable = 1
                logger.info(f"{motor_name} (ID {sid}): P={pgain}, torque ON")

    def start(self):
        self.robot = LeLampFollower(self.robot_config)
        try:
            self.robot.connect(calibrate=False)
        except Exception as e:
            logger.warning(f"Robot connect (partial): {e}")

        # Configure servos directly — works even if connect() partially failed
        try:
            self._configure_servos_raw()
        except Exception as e:
            logger.warning(f"Raw configure failed: {e}")

        logger.info(f"Animation service connected to {self.port}")

        # Move base_pitch and elbow_pitch to startup position
        try:
            self.move_to(STARTUP_POSITION, duration=STARTUP_MOVE_DURATION)
            logger.info("Servos 2,3 moved to startup position")
        except Exception as e:
            logger.warning(f"Failed to move to startup position: {e}")

        # Full joint state from hardware. move_to() only targets 2 joints; interpolation
        # used to assume missing joints were at 0° → large erratic moves and servo stall on device.
        self._sync_state_from_hardware()

        # Start event processing thread
        self._running.set()
        self._event_thread = threading.Thread(target=self._event_loop, daemon=True)
        self._event_thread.start()

        # Auto-play idle (same as upstream) so lamp moves immediately after boot
        self.dispatch("play", self.idle_recording)

    def stop(self, timeout: float = 5.0):
        # Stop event processing
        self._running.clear()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=timeout)
        
        if self.robot:
            self.robot.disconnect()
            self.robot = None

    def _sync_state_from_hardware(self) -> None:
        """Set _current_state from Present_Position for all joints.

        Required before interpolating to a recording: partial state with missing keys
        was treated as 0°, causing violent corrections and mechanical jam / overload.
        """
        if not self.robot:
            return
        try:
            with self.bus_lock:
                pos = _motor_positions_from_bus(self.robot)
            if pos:
                self._current_state = pos
        except Exception as e:
            logger.warning(f"sync state from hardware failed: {e}")
    
    def dispatch(self, event_type: str, payload: Any):
        """Dispatch an event - same interface as ServiceBase"""
        if not self._running.is_set():
            print(f"Animation service is not running, ignoring event {event_type}")
            return
        
        with self._event_lock:
            self._event_queue.append((event_type, payload))
    
    def _event_loop(self):
        """Custom event loop that supports interruption"""
        while self._running.is_set():
            # Check for events
            with self._event_lock:
                if self._event_queue:
                    event_type, payload = self._event_queue.pop(0)
                else:
                    event_type, payload = None, None
            
            if event_type:
                try:
                    self.handle_event(event_type, payload)
                except Exception as e:
                    print(f"Error handling event {event_type}: {e}")
            
            # Continue current playback
            self._continue_playback()
            
            time.sleep(1.0 / self.fps)  # Frame rate timing
    
    def handle_event(self, event_type: str, payload: Any):
        if event_type == "play":
            self._handle_play(payload)
        elif event_type == "music_start":
            self._handle_music_start()
        elif event_type == "music_stop":
            self._handle_music_stop()
        else:
            print(f"Unknown event type: {event_type}")

    def _handle_music_start(self):
        """Start grooving to music — loops music_groove until music stops."""
        self._music_playing = True
        self._handle_play(self._music_recording)

    def _handle_music_stop(self):
        """Stop music groove — return to idle."""
        self._music_playing = False
    
    def _handle_play(self, recording_name: str):
        """Start playing a recording with interpolation from current state"""
        if not self.robot:
            print("Robot not connected")
            return

        # Load the recording
        actions = self._load_recording(recording_name)
        if actions is None:
            return
        
        print(f"Starting {recording_name} with interpolation")
        
        # Set up new playback
        self._current_recording = recording_name
        self._current_actions = actions
        self._current_frame_index = 0
        
        # If we have a current state, set up interpolation to the first frame
        if self._current_state is not None:
            self._interpolation_frames = int(self.duration * self.fps)
            self._interpolation_target = actions[0]
        else:
            self._interpolation_frames = 0
            self._interpolation_target = None
    
    def freeze(self):
        """Pause servo writes so camera can capture a stable frame."""
        self._frozen.set()

    def unfreeze(self):
        """Resume servo writes after camera capture."""
        self._frozen.clear()

    def _continue_playback(self):
        """Continue current playback - called every frame"""
        if not self._current_recording or not self._current_actions:
            return

        # Skip servo writes while frozen (camera stabilization)
        if self._frozen.is_set():
            return
        
        try:
            # Handle interpolation to first frame
            if self._interpolation_frames > 0 and self._interpolation_target is not None:
                # Calculate interpolation progress
                progress = 1.0 - (self._interpolation_frames / (self.duration * self.fps))
                progress = max(0.0, min(1.0, progress))
                
                # Interpolate between current state and target
                interpolated_action = {}
                for joint in self._interpolation_target.keys():
                    # Default 0 is unsafe if _current_state is incomplete (see _sync_state_from_hardware).
                    current_val = self._current_state.get(joint) if self._current_state else None
                    if current_val is None:
                        logger.warning(
                            "interpolation: joint %s missing from _current_state, using 0 (risk of jam)",
                            joint,
                        )
                        current_val = 0.0
                    target_val = self._interpolation_target[joint]
                    interpolated_action[joint] = current_val + (target_val - current_val) * progress
                
                with self.bus_lock:
                    self.robot.send_action(interpolated_action)
                self._current_state = interpolated_action.copy()
                self._interpolation_frames -= 1
                return

            # Play current frame
            if self._current_frame_index < len(self._current_actions):
                action = self._current_actions[self._current_frame_index]
                with self.bus_lock:
                    self.robot.send_action(action)
                self._current_state = action.copy()
                self._current_frame_index += 1
            else:
                # Recording finished
                if self._music_playing and self._current_recording == self._music_recording:
                    # Loop music groove while music is playing
                    self._current_frame_index = 0
                elif self._current_recording != self.idle_recording:
                    # Interpolate back to idle (or music groove if music started)
                    if self._music_playing:
                        next_rec = self._music_recording
                    else:
                        next_rec = self.idle_recording
                    next_actions = self._load_recording(next_rec)
                    if next_actions is not None and len(next_actions) > 0:
                        self._current_recording = next_rec
                        self._current_actions = next_actions
                        self._current_frame_index = 0
                        if self._current_state is not None:
                            self._interpolation_frames = int(self.duration * self.fps)
                            self._interpolation_target = next_actions[0]
                else:
                    # Loop idle recording
                    self._current_frame_index = 0
                    
        except Exception as e:
            logger.exception("playback error: %s", e)
            # Reset to safe state
            self._current_recording = None
            self._current_actions = []
            self._current_frame_index = 0
    
    def get_available_recordings(self) -> List[str]:
        """Get list of recording names available for this lamp ID"""
        if not os.path.exists(self.recordings_dir):
            return []
        
        recordings = []
        suffix = f".csv"
        
        for filename in os.listdir(self.recordings_dir):
            if filename.endswith(suffix):
                # Remove the lamp_id suffix to get the recording name
                recording_name = filename[:-len(suffix)]
                recordings.append(recording_name)
        
        return sorted(recordings)
    
    def _load_recording(self, recording_name: str) -> Optional[List[Dict[str, float]]]:
        """Load a recording from cache or file"""
        # Check cache first
        if recording_name in self._recording_cache:
            return self._recording_cache[recording_name]

        csv_filename = f"{recording_name}.csv"
        csv_path = os.path.join(self.recordings_dir, csv_filename)

        if not os.path.exists(csv_path):
            logger.warning(f"Recording not found: {csv_path}")
            return None

        try:
            with open(csv_path, 'r') as csvfile:
                csv_reader = csv.DictReader(csvfile)
                actions = []
                for row in csv_reader:
                    # Extract action data (exclude timestamp column)
                    action = {key: float(value) for key, value in row.items() if key != 'timestamp'}
                    actions.append(action)

            # Cache the recording
            self._recording_cache[recording_name] = actions
            return actions

        except Exception as e:
            logger.error(f"Error loading recording {recording_name}: {e}")
            return None

    def move_to(self, target_positions: Dict[str, float], duration: float = DEFAULT_MOVE_DURATION):
        """Smoothly move servos to target positions using software interpolation.

        Instead of sending the target in one shot (which causes jerky instant jumps),
        this method reads the current position and interpolates at self.fps over the
        given duration — the same approach used for animation playback.

        Args:
            target_positions: dict of joint positions, e.g. {"base_yaw.pos": 0.0, ...}
            duration: time in seconds to reach the target (default 2.0)
        """
        if not self.robot:
            raise RuntimeError("Robot not connected")

        # Read current positions (bus-only; avoid get_observation camera reads)
        try:
            with self.bus_lock:
                current = _motor_positions_from_bus(self.robot)
            if not current:
                raise ValueError("empty Present_Position read")
        except Exception:
            # Fallback: use last known state or jump directly
            if self._current_state:
                current = self._current_state.copy()
            else:
                with self.bus_lock:
                    self.robot.send_action(target_positions)
                return

        total_frames = max(1, int(duration * self.fps))

        for frame in range(1, total_frames + 1):
            t0 = time.perf_counter()
            progress = frame / total_frames

            interpolated = {}
            for joint, target_val in target_positions.items():
                cur_val = current.get(joint, target_val)
                interpolated[joint] = cur_val + (target_val - cur_val) * progress

            try:
                with self.bus_lock:
                    self.robot.send_action(interpolated)
            except Exception as e:
                logger.warning(f"Interpolated move frame {frame} failed: {e}")
                break

            dt = time.perf_counter() - t0
            sleep_time = (1.0 / self.fps) - dt
            if sleep_time > 0:
                time.sleep(sleep_time)

        # Send final target exactly
        try:
            with self.bus_lock:
                self.robot.send_action(target_positions)
        except Exception:
            pass

        # Prefer full pose from hardware so other joints are not left stale
        try:
            with self.bus_lock:
                pos = _motor_positions_from_bus(self.robot)
            if pos:
                self._current_state = pos
                return
        except Exception as e:
            logger.warning(f"move_to: could not read full state after move: {e}")
        self._current_state = target_positions.copy()
    