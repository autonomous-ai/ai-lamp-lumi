import { Field, SectionCard } from "./shared";

export function DeviceSection({
  active, deviceId, setDeviceId, mac,
}: {
  active: boolean;
  deviceId: string;
  setDeviceId: (v: string) => void;
  mac?: string;
}) {
  return (
    <SectionCard id="device" title="Device" active={active}>
      <Field label="Device ID" id="device_id" value={deviceId} onChange={setDeviceId} placeholder="lumi-001" readOnly />
      <Field label="MAC" id="mac" value={mac ?? ""} onChange={() => {}} placeholder="Lumi-XXXX" readOnly />
    </SectionCard>
  );
}
