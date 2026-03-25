#!/bin/bash

TOKEN="8460619616:AAFA9m2X5ac_i2hrdElaDdbmpd4--wSWuog"
CHAT_ID="1042638334"
MAC_ADDR=$(cat /sys/class/net/wlan0/address)
IP=$(hostname -I | awk '{print $1}')
SSID=$(iwgetid -r)
curl -s -X POST https://api.telegram.org/bot$TOKEN/sendMessage -d chat_id=$CHAT_ID -d text="Raspberry Pi $MAC_ADDR with SSID: $SSID, IP: $IP"