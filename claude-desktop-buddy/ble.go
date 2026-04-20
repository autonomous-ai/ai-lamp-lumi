package main

import (
	"bufio"
	"bytes"
	"log"

	"tinygo.org/x/bluetooth"
)

var adapter = bluetooth.DefaultAdapter

// Nordic UART Service UUIDs
var (
	nusServiceUUID = bluetooth.NewUUID([16]byte{
		0x6e, 0x40, 0x00, 0x01, 0xb5, 0xa3, 0xf3, 0x93,
		0xe0, 0xa9, 0xe5, 0x0e, 0x24, 0xdc, 0xca, 0x9e,
	})
	nusRXUUID = bluetooth.NewUUID([16]byte{
		0x6e, 0x40, 0x00, 0x02, 0xb5, 0xa3, 0xf3, 0x93,
		0xe0, 0xa9, 0xe5, 0x0e, 0x24, 0xdc, 0xca, 0x9e,
	})
	nusTXUUID = bluetooth.NewUUID([16]byte{
		0x6e, 0x40, 0x00, 0x03, 0xb5, 0xa3, 0xf3, 0x93,
		0xe0, 0xa9, 0xe5, 0x0e, 0x24, 0xdc, 0xca, 0x9e,
	})
)

// BLEServer manages the Nordic UART BLE GATT server.
type BLEServer struct {
	deviceName  string
	txChar      bluetooth.Characteristic
	onMessage   func([]byte)                        // called for each complete JSON line received
	onConnect   func(device bluetooth.Device, connected bool) // called on connect/disconnect
	rxBuf       bytes.Buffer                        // accumulates partial lines
}

func NewBLEServer(deviceName string, onMessage func([]byte), onConnect func(bluetooth.Device, bool)) *BLEServer {
	return &BLEServer{
		deviceName: deviceName,
		onMessage:  onMessage,
		onConnect:  onConnect,
	}
}

// Start initializes the BLE adapter and begins advertising.
func (s *BLEServer) Start() error {
	log.Println("[ble] enabling adapter...")
	if err := adapter.Enable(); err != nil {
		return err
	}

	// Set connect/disconnect handler
	adapter.SetConnectHandler(func(device bluetooth.Device, connected bool) {
		if connected {
			log.Println("[ble] device connected")
		} else {
			log.Println("[ble] device disconnected")
		}
		if s.onConnect != nil {
			s.onConnect(device, connected)
		}
	})

	// Add Nordic UART Service
	err := adapter.AddService(&bluetooth.Service{
		UUID: nusServiceUUID,
		Characteristics: []bluetooth.CharacteristicConfig{
			{
				UUID:  nusRXUUID, // Desktop writes here (Desktop → Device)
				Flags: bluetooth.CharacteristicWritePermission | bluetooth.CharacteristicWriteWithoutResponsePermission,
				WriteEvent: func(client bluetooth.Connection, offset int, value []byte) {
					s.handleRX(value)
				},
			},
			{
				Handle: &s.txChar,
				UUID:   nusTXUUID, // Device writes here (Device → Desktop)
				Flags:  bluetooth.CharacteristicNotifyPermission | bluetooth.CharacteristicReadPermission,
			},
		},
	})
	if err != nil {
		return err
	}

	log.Printf("[ble] advertising as %q...", s.deviceName)
	adv := adapter.DefaultAdvertisement()
	err = adv.Configure(bluetooth.AdvertisementOptions{
		LocalName:    s.deviceName,
		ServiceUUIDs: []bluetooth.UUID{nusServiceUUID},
	})
	if err != nil {
		return err
	}

	return adv.Start()
}

// handleRX accumulates incoming bytes and dispatches complete JSON lines.
func (s *BLEServer) handleRX(data []byte) {
	s.rxBuf.Write(data)

	scanner := bufio.NewScanner(&s.rxBuf)
	var remaining []byte
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		// Make a copy since scanner reuses buffer
		msg := make([]byte, len(line))
		copy(msg, line)
		if s.onMessage != nil {
			s.onMessage(msg)
		}
	}

	// Keep any incomplete data in buffer
	if s.rxBuf.Len() > 0 {
		remaining = make([]byte, s.rxBuf.Len())
		copy(remaining, s.rxBuf.Bytes())
	}
	s.rxBuf.Reset()
	if remaining != nil {
		s.rxBuf.Write(remaining)
	}
}

// Send writes a JSON line to the TX characteristic (Device → Desktop).
// BLE MTU is typically 20 bytes, so we chunk if needed.
func (s *BLEServer) Send(data []byte) error {
	const mtu = 20
	for len(data) > 0 {
		chunk := data
		if len(chunk) > mtu {
			chunk = data[:mtu]
		}
		if _, err := s.txChar.Write(chunk); err != nil {
			return err
		}
		data = data[len(chunk):]
	}
	return nil
}
