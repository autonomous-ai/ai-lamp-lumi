echo "========== Upload Built Application... =========="
# scp to user-writable path, then sudo mv (user cannot write directly to /usr/local/bin)
sshpass -p "12345" scp ./bootstrap-server system@192.168.1.16:/tmp/bootstrap-server
sshpass -p "12345" ssh system@192.168.1.16 'sudo mv -f /tmp/bootstrap-server /usr/local/bin/bootstrap-server && sudo chmod 755 /usr/local/bin/bootstrap-server'
echo "========== Restart service =========="
sshpass -p "12345" ssh system@192.168.1.16 'sudo systemctl restart bootstrap'