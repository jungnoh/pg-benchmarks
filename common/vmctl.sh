#!/bin/bash

QEMU_SSH_PORT=5555
QEMU_GDB_PORT=1235

BOOT_IMG_PATH=/home/jungnoh/cache_ext/linux/arch/x86/boot/bzImage
KERNEL_IMG_PATH=/home/jungnoh/djournalplus.code/tools/qemu/vm_imgs/qemu-image.qcow2
VM_SHARED_PATH=/home/jungnoh/pg-benchmarks/vm-shared

PSQL_VM_PORT=5432
PSQL_HOST_PORT=35432

NVME_PCIE_ADDR="0000:3b:00.0" # Set proper PCIE address for your NVMe device.

case "$1" in
    start)
        if [ $# -ne 3 ]; then
            echo "Usage: $0 start <cpu_count> <memory_gb>"
            echo "Example: $0 start 32 64"
            exit 1
        fi

        CPU_COUNT="$2"
        TOTAL_MEM="${3}G"

        # numactl --cpunodebind=0 --membind=0 \
        qemu-system-x86_64 -kernel "$BOOT_IMG_PATH" \
            -cpu host \
            -smp cpus="$CPU_COUNT" \
            -drive file="$KERNEL_IMG_PATH",index=0,media=disk,format=qcow2 \
            -m "$TOTAL_MEM" \
            -append "root=/dev/sda rw console=ttyS0 selinux=0" \
            --enable-kvm \
            --nographic \
            -netdev user,id=net0,restrict=off,hostfwd=tcp::$QEMU_SSH_PORT-:22,hostfwd=tcp::$PSQL_HOST_PORT-:$PSQL_VM_PORT \
            -device virtio-net-pci,netdev=net0 \
            -mem-prealloc \
            -gdb tcp::$QEMU_GDB_PORT  \
            -device vfio-pci,host=$NVME_PCIE_ADDR \
            -virtfs local,path=$VM_SHARED_PATH,mount_tag=hostshare,security_model=mapped-xattr
            # Mount with: sudo mkdir -p /mnt/hostshare && sudo mount -t 9p -o trans=virtio hostshare /mnt/hostshare
        ;;
    stop)
        sudo pkill -9 qemu-system-x86
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        echo "  start <cpu_count> <memory_gb> - Start the VM"
        echo "  stop                          - Stop the VM"
        exit 1
        ;;
esac
