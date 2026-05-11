import { Field, SectionCard } from "./shared";

export function DeviceSection({
  active, deviceId, setDeviceId,
}: {
  active: boolean;
  deviceId: string;
  setDeviceId: (v: string) => void;
}) {
  return (
    <SectionCard id="device" title="Device" active={active}>
      <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" readOnly />
    </SectionCard>
  );
}
