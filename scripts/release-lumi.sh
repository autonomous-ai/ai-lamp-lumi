echo "========== Upload Built Application... =========="
# scp to user-writable path, then sudo mv (user cannot write directly to /usr/local/bin)
sshpass -p "12345" scp ./lumi-server system@172.168.20.109:/tmp/lumi-server
sshpass -p "12345" ssh system@172.168.20.109 'sudo mv -f /tmp/lumi-server /usr/local/bin/lumi-server && sudo chmod 755 /usr/local/bin/lumi-server'
echo "========== Restart service =========="
sshpass -p "12345" ssh system@172.168.20.109 'sudo systemctl restart lumi'
