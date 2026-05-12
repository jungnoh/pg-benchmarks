#!/bin/bash

SCREEN_SESS_NAME=pg-benchmark-vm

QEMU_SSH_PORT=5555
QEMU_GDB_PORT=1235

BOOT_IMG_PATH=/mnt/cache-ext-workspace/vm-data/bzImage
KERNEL_IMG_PATH=/mnt/cache-ext-workspace/vm-data/qemu-image.qcow2
VM_SHARED_PATH=/mnt/cache-ext-workspace/vm-data/shared

PSQL_VM_PORT=5432
PSQL_HOST_PORT=35432

PSQL_EXPORTER_VM_PORT=9187
PSQL_EXPORTER_HOST_PORT=39187

NODE_EXPORTER_VM_PORT=9100
NODE_EXPORTER_HOST_PORT=39100

NVME_PCIE_ADDR="0000:af:00.0" # Set proper PCIE address for your NVMe device.

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
        screen -dmS "$SCREEN_SESS_NAME"  \
	qemu-system-x86_64 -kernel "$BOOT_IMG_PATH" \
            -cpu host \
            -smp cpus="$CPU_COUNT" \
            -drive file="$KERNEL_IMG_PATH",index=0,media=disk,format=qcow2 \
            -m "$TOTAL_MEM" \
            -append "root=/dev/sda rw console=ttyS0 selinux=0" \
            --enable-kvm \
            --nographic \
            -netdev user,id=net0,restrict=off,hostfwd=tcp::$QEMU_SSH_PORT-:22,hostfwd=tcp::$PSQL_HOST_PORT-:$PSQL_VM_PORT,hostfwd=tcp::$PSQL_EXPORTER_HOST_PORT-:$PSQL_EXPORTER_VM_PORT,hostfwd=tcp::$NODE_EXPORTER_HOST_PORT-:$NODE_EXPORTER_VM_PORT \
            -device virtio-net-pci,netdev=net0 \
            -mem-prealloc \
            -gdb tcp::$QEMU_GDB_PORT  \
            -device vfio-pci,host=$NVME_PCIE_ADDR \
            -virtfs local,path=$VM_SHARED_PATH,mount_tag=hostshare,security_model=mapped-xattr
            # Mount with: sudo mkdir -p /mnt/hostshare && sudo mount -t 9p -o trans=virtio hostshare /mnt/hostshare
        ;;
    stop)
        # sudo pkill -9 qemu-system-x86
	screen -X -S "$SCREEN_SESS_NAME" quit
        ;;
    status)
        # Filter for QEMU instances started by this script — match the
        # unique 9p virtfs share signature so we ignore unrelated VMs
        # that may also be running on the host.
        VMCTL_FINGERPRINT="path=${VM_SHARED_PATH},mount_tag=hostshare"
        QEMU_PIDS=$(pgrep -f "qemu-system-x86_64.*${VMCTL_FINGERPRINT}")
        if [ -z "$QEMU_PIDS" ]; then
            echo "No vmctl-started VM is running (looked for ${VMCTL_FINGERPRINT})" >&2
            exit 1
        fi
        QEMU_PID=$(echo "$QEMU_PIDS" | head -n1)
        CMDLINE=$(tr '\0' ' ' < /proc/$QEMU_PID/cmdline)

        # Extract the value token following `-smp`. Accepts:
        #   -smp 32                          -> 32
        #   -smp cpus=32                     -> 32
        #   -smp cpus=32,sockets=1,...       -> 32
        #   -smp 32,sockets=1,...            -> 32
        SMP_VAL=$(echo "$CMDLINE" | grep -oE '(^| )-smp +[^ ]+' | head -n1 | awk '{print $2}')
        CPU=$(echo "$SMP_VAL" | grep -oE 'cpus=[0-9]+' | head -n1 | cut -d= -f2)
        if [ -z "$CPU" ]; then
            CPU=$(echo "$SMP_VAL" | grep -oE '^[0-9]+')
        fi

        # Extract the value token following `-m`. Accepts:
        #   -m 64G  /  -m 64g  /  -m 64M  /  -m 65536
        # Strips an optional G/g/M/m suffix; if no suffix, treats the
        # number as megabytes (QEMU's default unit) and converts to GB.
        M_VAL=$(echo "$CMDLINE" | grep -oE '(^| )-m +[^ ]+' | head -n1 | awk '{print $2}')
        case "$M_VAL" in
            *[Gg]) MEM="${M_VAL%[Gg]}" ;;
            *[Mm]) MEM=$(( ${M_VAL%[Mm]} / 1024 )) ;;
            "")    MEM="" ;;
            *)     MEM=$(( M_VAL / 1024 )) ;;
        esac

        if [ -z "$CPU" ] || [ -z "$MEM" ]; then
            echo "Failed to parse CPU/MEM from QEMU cmdline" >&2
            echo "  -smp value: '$SMP_VAL' -> CPU='$CPU'" >&2
            echo "  -m   value: '$M_VAL'   -> MEM='$MEM'" >&2
            echo "  full cmdline:" >&2
            echo "  $CMDLINE" >&2
            exit 1
        fi
        echo "$CPU $MEM"
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        echo "  start <cpu_count> <memory_gb> - Start the VM"
        echo "  stop                          - Stop the VM"
        echo "  status                        - Print the running VM's <cpu> <memory_gb>"
        exit 1
        ;;
esac
