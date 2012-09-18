import os
import fabric.api
from fabric.api import task, execute, env, run, sudo
from fabric.utils import puts, warn, error
from fabric.contrib.console import confirm
from fabric.contrib.files import exists
from fabric.context_managers import settings, cd

def chroot(cmd):
    return sudo("chroot mnt/ %s" %cmd)

def chins(cmd):
    return sudo("chroot mnt/ apt-get install -y %s" %cmd)

def chbash(cmd):
    return sudo("echo '%s' | sudo bash" %cmd)

def root():
    if env.get("root"):
        return cd(env.get("root"))
    return cd(".")

@task
def prepare( size=2000 ):
    if exists("root.img"):
        if not confirm("Do you want to create new image?"):
            return

    local("dd if=/dev/zero of=root.img bs=1024k count=%d"% size)
    local("mkfs.ext4 -F -L root root.img")

    if not os.path.exists("mnt"):
        local("mkdir -p mnt")

@task
def resize( new_size=1800 ):
    mount(False)
    run("dd if=/dev/zero of=tmp.img bs=1024k count=%d"% new_size)
    run("mkfs.ext4 -F -L ubuntu tmp.img")
    run("mkdir -p tmp")
    sudo("mount -o loop tmp.img tmp/")
    sudo("cp -rv mnt/* ./tmp/")
    execute(unmount)
    run("rm root.img")
    sudo("umount tmp.img")
    run("mv tmp.img root.img")

@task
def mount(devices=True):
    if not exists("root.img"):
        if confirm("Root image does not seem to exist, create one?"):
            execute(prepare)

    local("mkdir -p mnt")

    execute(unmount)
    sudo("mount -o loop root.img mnt/")
    if devices:
        sudo("mkdir -p mnt/proc")
        sudo("mount -t proc proc mnt/proc")
        sudo("mkdir -p mnt/dev")
        sudo("mount --bind /dev mnt/dev")
        sudo("mkdir -p mnt/sys")
        sudo("mount -t sysfs sysfs mnt/sys")
        sudo("mount -t devpts /dev/pts mnt/dev/pts")

@task
def unmount():
    with settings(warn_only=True):
        sudo("sudo lsof -t mnt/ | sudo xargs -r kill")
        sudo("sudo chroot mnt/ /etc/init.d/udev stop")
        sudo("sudo chroot mnt/ /etc/init.d/cron stop")
        sudo("umount mnt/proc")
        sudo("umount mnt/sys")
        sudo("umount mnt/dev/pts")
        sudo("umount mnt/dev")
        sudo("umount mnt/")

@task
def debootstrap(release= None, target= None, mirror= None, target_arch= None, password= None):
    opts = dict(
            release= release or env.get("release") or "oneiric",
            target= target or env.get("target") or "mnt",
            mirror= mirror or env.get("mirror") or "http://de.archive.ubuntu.com/ubuntu/",
            target_arch= target_arch or env.get("target_arch") or "amd64",
            password= password or env.get("password") or "root"
            )

    if not exists("mnt/dev"):
        if not exists("root.img"):
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
        ret= sudo("debootstrap --arch %(target_arch)s %(release)s %(target)s %(mirror)s" % opts)

        if ret.return_code!=2 and ret.return_code==0:
            error("Problem running debootstrap!")

@task
def install(password= None, start_ssh=True):
    opts = dict(
            password= password or env.get("password") or "root",
            start_ssh= start_ssh or env.get("start_ssh")
            )

    puts("Configuring...")
    if not exists("templates/sources.list"):
        chbash("""cat >> mnt/etc/apt/sources.list <<EOF
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs) main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs)-security main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $(lsb_release -cs)-updates main restricted universe multiverse
deb http://archive.canonical.com/ubuntu $(lsb_release -cs) partner
EOF\n
               """)
    else:
        sudo("cp templates/sources.list mnt/etc/apt/sources.list")
    if not exists("templates/interfaces"):
        pass
    else:
        sudo("cp templates/intefaces mnt/etc/network/interfaces")
    sudo("cp /etc/mtab mnt/etc/mtab")
    chbash("""cat >> mnt/etc/apt/apt.conf.d/10periodic <<EOF
APT::Periodic::Enable "1";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "5";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::RandomSleep "1800";
EOF\n
           """)
    chroot("passwd << EOF\n%(password)s\n%(password)s\nEOF\n" % opts)

    puts("Installing packages...")
    chroot("apt-get update -y")
    chins("linux-image")

    chins("udev")
    chbash("echo \"none /dev/pts devpts defaults 0 0\" >> mnt/etc/fstab")
    chbash("echo \"none /proc proc defaults\" >> mnt/etc/fstab")

    chins("vim nano joe screen unattended-upgrades \
    	   smartmontools ntp ssh openssh-server")

    sudo("sudo lsof -t mnt/ | sudo xargs -r kill")

    if opts["start_ssh"]:
        chbash("sed -i \"s/Port 22/Port 23/g\" mnt/etc/ssh/sshd_config")
        chroot("/etc/init.d/ssh start")

@task
def flash(root= None, swap= None, home= None):
    opts = dict(
            root= root or env.get("root") or "/dev/sdb1",
            swap= swap or env.get("swap") or "/dev/sdb2",
            home= home or env.get("home") or None
            )
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
    sudo("dd if=root.img of=%(root)s" %opts)

    puts("Installing grub...")
    chins("grub-pc")
    execute(unmount)

    puts("Writing image back...")
    sudo("dd if=%(root)s of=root.img")
