# Set of scripts that helps me making my ubuntu live usb bootable drives

## Script description

* prepare - Prepares images( root.img )
* mountall - Mounts images and devices
* unmountall - Unmounts images and devices
* install - Installs ubuntu on images
* flash - Flashes image to device
* mkfstab - Creates fstab based on device UUIDS( needs $ROOT, $HOME, $SWAP)
* mkgrub - Installs grub on real device( needs $ROOT, HOME, $SWAP )
