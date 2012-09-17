import os
import fabric.api
from fabric.api import task, execute, env
from fabric.utils import puts, warn, error
from fabric.contrib.console import confirm
from fabric.context_managers import settings

def local(cmd, use_sudo=False):
    if use_sudo:
        return fabric.api.local("sudo "+cmd)
    else:
        return fabric.api.local(cmd)

@task
def prepare( size=2000 ):
    if os.path.exists("root.img"):
        if not confirm("Do you want to create new image?"):
            return

    local("dd if=/dev/zero of=root.img bs=1024k count=%d"% size)
    local("mkfs.ext4 -L root root.img")

    if not os.path.exists("mnt"):
        local("mkdir -p mnt")

@task
def mount():
    if not os.path.exists("root.img"):
        if confirm("Root image does not seem to exist, create one?"):
            prepare()

    if not os.path.exists("mnt"):
        local("mkdir -p mnt")

    execute(unmount)
    local("mount -o loop root.img mnt/", use_sudo=True)
    local("mkdir -p mnt/proc", use_sudo=True)
    local("mount -t proc proc mnt/proc", use_sudo=True)
    local("mkdir -p mnt/dev", use_sudo=True)
    local("mount --bind /dev mnt/dev", use_sudo=True)
    local("mkdir -p mnt/sys", use_sudo=True)
    local("mount -t sysfs sysfs mnt/sys", use_sudo=True)

@task
def unmount():
    with settings(warn_only=True):
        local("umount mnt/proc", use_sudo=True)
        local("umount mnt/sys", use_sudo=True)
        local("umount mnt/sys", use_sudo=True)
        local("umount mnt/")

@task
def install(release= None, target= None, mirror= None, target_arch= None, password= None):
    opts = dict(
            release= release or env.get("release") or "oneiric",
            target= target or env.get("target") or "mnt",
            mirror= mirror or env.get("mirror") or "http://de.archive.ubuntu.com/ubuntu/",
            target_arch= target_arch or env.get("target_arch") or "amd64",
            password= password or env.get("password") or "root"
            )

    if not os.path.exists("mnt/dev"):
        if not os.path.exists("root.img"):
            warn("Your image does not seem to exist...")
            if confirm("Should i create one?"):
                execute(prepare)

        warn("Your image does not seem to be mounted...")
        if confirm("Should i mount it?"):
            execute(mount)


    puts("""Debootstraping release=%(release)s
         target=%(target)s mirror=%(mirror)s
         target_arch=%(target_arch)s""" % opts)
    with settings(warn_only=True):
        ret= local("debootstrap --arch %(target_arch)s %(release)s %(target)s %(mirror)s" % opts,
         use_sudo= True)

        if ret.return_code!=2 and ret.return_code==0:
            error("Problem running debootstrap!")

    chroot= lambda x: local("chroot mnt/ "+ x, use_sudo=True)
    chins= lambda x: local("chroot mnt/ apt-get install -y", use_sudo=True)
    chbash = lambda x: local("echo '%s' | sudo bash" % x)

    puts("Configuring...")
    if not os.path.exists("templates/sources.list"):
        chbash("""cat >> mnt/etc/apt/sources.list <<EOF
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs) main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs)-security main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs)-updates main restricted universe multiverse
deb http://archive.canonical.com/ubuntu $(lsb_release -cs) partner
EOF\n
               """)
    else:
        local("cp templates/sources.list mnt/etc/apt/sources.list", use_sudo=True)
    if not os.path.exists("templates/interfaces"):
        pass
    else:
        local("cp templates/intefaces mnt/etc/network/interfaces", use_sudo=True)
    local("cp /etc/mtab mnt/etc/mtab", use_sudo=True)
    chbash("""cat >> mnt/etc/apt/apt.conf.d/10periodic <<EOF
APT::Periodic::Enable "1";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "5";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::RandomSleep "1800";
EOF\n
           """)
    chroot("echo \"%(password)s\" | passwd --stdin" % opts)

    puts("Installing packages...")
    chroot("apt-get update -y")
    chroot("linux-image")
    chins("""vim nano joe screen htop unattended-upgrades python-software-properties
             mdadm lvm2 smartmontools nmap ntp traceroute ssh""")

@task
def flash(root= None, swap= None, home= None):
    opts = dict(
            root= root or env.get("root") or "/dev/sdb1",
            swap= swap or env.get("swap") or "/dev/sdb2",
            home= home or env.get("home") or None
            )
    chins= lambda x: local("chroot mnt/ apt-get install -y", use_sudo=True)
    chroot= lambda x: local("chroot mnt/ "+ x, use_sudo=True)
    chbash = lambda x: local("echo '%s' | sudo bash" % x)

    if not os.path.exists("mnt/dev"):
        if not os.path.exists("root.img"):
            error("Your image does not seem to exist...")

        warn("Your image does not seem to be mounted...")
        if confirm("Should i mount it?"):
            execute(mount)

    puts("Wrinting image: rootfs=%(root)s, swap=%(swap)s, home=%(home)s" %opts)
    if opts["home"]:
        fstab="""cat > mnt/etc/fstab <<EOF
# device mount   type options freq passno
UUID=$(blkid -o value -s UUID %(root)s) /       ext4 errors=remount-ro,user_xattr 0 1
UUID=$(blkid -o value -s UUID %(swap)s) none    swap    sw                        0 0
UUID=$(blkid -o value -s UUID %(home)s /home   ext4 defaults                     0 0
EOF\n
               """
    else:
        fstab="""cat > mnt/etc/fstab <<EOF
# device mount   type options freq passno
UUID=$(blkid -o value -s UUID %(root)s) /       ext4 errors=remount-ro,user_xattr 0 1
UUID=$(blkid -o value -s UUID %(swap)s) none    swap    sw                        0 0
EOF\n
               """
    puts("fstab:\n"+fstab)
    chbash(fstab)

    puts("Writing image to flash drive...")
    local("dd if=root.img of=%(root)s" %opts, use_sudo=True)

    puts("Installing grub...")
    chins("grub-pc")
    execute(unmount)

    puts("Writing image back...")
    local("dd if=%(root)s of=root.img", use_sudo=True)
