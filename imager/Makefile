build:
	# Build the Docker build environment
	docker build -t pi-builder .

	# Run it — needs --privileged for losetup/mount
	docker run --rm \
	--privileged \
	-v ./output:/output \
	pi-builder

sd-card-list:
	diskutil list

sd-card-test:
ifndef DISK
	$(error DISK is required. Usage: make sd-card-test DISK=19)
endif
	@echo "==> Testing SD card write (100 MB of zeros)..."
	sudo launchctl unload /System/Library/LaunchDaemons/com.apple.diskarbitrationd.plist 2>/dev/null || true
	diskutil unmountDisk /dev/disk$(DISK) 2>/dev/null || true
	sleep 1
	sudo dd if=/dev/zero of=/dev/rdisk$(DISK) bs=1m count=1000 status=progress; \
	DD_EXIT=$$?; \
	sudo launchctl load /System/Library/LaunchDaemons/com.apple.diskarbitrationd.plist 2>/dev/null || true; \
	if [ $$DD_EXIT -eq 0 ]; then echo "==> SD card OK — hardware is fine"; else echo "==> SD card FAILED — hardware issue (bad card or reader)"; fi; \
	exit $$DD_EXIT

sd-card-flash:
ifndef DISK
	$(error DISK is required. Usage: make sd-card-flash DISK=4)
endif
	@echo "==> Flashing golden.img to /dev/disk$(DISK)..."
	diskutil unmountDisk force /dev/disk$(DISK)
	sudo dd if=./output/golden.img of=/dev/disk$(DISK) bs=64m conv=fsync status=progress
	sync
	diskutil eject /dev/disk$(DISK) 2>/dev/null || true
	@echo "==> Flash complete"
