## Restart bluetooth on board
sudo systemctl stop lumi-buddy
sudo systemctl restart bluetooth
sleep 3
sudo bluetoothctl power on
sudo systemctl start lumi-buddy