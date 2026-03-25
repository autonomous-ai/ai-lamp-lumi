echo "========== Upload Built Application... =========="
# scp to user-writable path, then sudo mv (user cannot write directly to /usr/local/bin)
sshpass -p "12345" scp ./intern-server system@172.168.20.109:/tmp/intern-server
sshpass -p "12345" ssh system@172.168.20.109 'sudo mv -f /tmp/intern-server /usr/local/bin/intern-server && sudo chmod 755 /usr/local/bin/intern-server'
echo "========== Restart service =========="
sshpass -p "12345" ssh system@172.168.20.109 'sudo systemctl restart intern'