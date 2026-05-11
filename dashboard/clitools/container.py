import argparse
import os

LOGS = '/ylstackos/logs'

def flyoscontainer_execute(container_name, cmd=None):
    if not cmd:
        shellrc_path = f'/container/list/{container_name}/etc/ylstackos/shellrc.conf'
        if not os.path.exists(shellrc_path):
            raise FileNotFoundError(f"Container {container_name} not found.")
        shellrc = open(shellrc_path).read()
        cmd = shellrc
    try:
        os.system(f'chroot /container/list/{container_name} {cmd}')
    except FileNotFoundError as e:
        print(e)

def flyoscontainer_start(container_name):
    try:
        shellrc_path = f'/container/list/{container_name}/etc/ylstackos/shellrc.conf'
        if not os.path.exists(shellrc_path):
            raise FileNotFoundError(f"Container {container_name} not found.")
        os.system(f'''
        export CONTAINERROOT="/container/list/{container_name}"
        chmod 755 $CONTAINERROOT/etc/ylstackos/*
        nohup bash $CONTAINERROOT/etc/ylstackos/start.sh >> {LOGS}/flycontainer_startservice_{container_name}.log 2>&1 &
        nohup chroot $CONTAINERROOT /etc/ylstackos/init.sh >> {LOGS}/flycontainer_init_{container_name}.log 2>&1 &
        ''')
        print(f'Container {container_name} started.')
    except FileNotFoundError as e:
        print(e)

def flyoscontainer_stop(container_name):
    try:
        shellrc_path = f'/container/list/{container_name}/etc/ylstackos/shellrc.conf'
        if not os.path.exists(shellrc_path):
            raise FileNotFoundError(f"Container {container_name} not found.")
        os.system(f'''
        export CONTAINERROOT="/container/list/{container_name}"
        chmod 755 $CONTAINERROOT/etc/ylstackos/*
        nohup bash $CONTAINERROOT/etc/ylstackos/stop.sh >> {LOGS}/flycontainer_stopservice_{container_name}.log 2>&1 &
        ''')
        print(f'Container {container_name} stopped.')
    except FileNotFoundError as e:
        print(e)

def flyoscontainer_delete(container_name):
    try:
        os.system(f"rm -rf /container/list/{container_name}")
        print(f'Container {container_name} deleted successfully.')
    except FileNotFoundError as e:
        print(e)

def flyoscontainer_createnew(name, path):
    try:
        if os.path.exists(f'/container/list/{name}'):
            raise FileExistsError(f'This container name already exists.')
        if '.flycontainer' not in path:
            raise ValueError('Please enter a valid container file system image path (*.flycontainer)')
        os.mkdir(f'/container/list/{name}')
        os.system(f'tar -zxvf {path} -C /container/list/{name}')
        print(f'Container {name} created successfully.')
    except (FileExistsError, ValueError) as e:
        print(e)

def main():
    parser = argparse.ArgumentParser(description='CLI for managing YL StackOS containers')
    parser.add_argument('action', choices=['login', 'start', 'stop', 'delete', 'create', 'cmd'],
                        help='Action to perform on the container')
    parser.add_argument('container_name', nargs='?', help='Name of the container')
    parser.add_argument('--name', help='Name of the new container')
    parser.add_argument('--path', help='Path to the container file system image')
    parser.add_argument('--cmd', help='Command to execute within the container')

    args, unknown = parser.parse_known_args()

    if args.action == 'login':
        flyoscontainer_execute(args.container_name)
    elif args.action == 'start':
        flyoscontainer_start(args.container_name)
    elif args.action == 'stop':
        flyoscontainer_stop(args.container_name)
    elif args.action == 'delete':
        flyoscontainer_delete(args.container_name)
    elif args.action == 'create':
        flyoscontainer_createnew(args.name, args.path)
    elif args.action == 'cmd':
        cmd = ' '.join([args.cmd] + unknown)
        flyoscontainer_execute(args.container_name, cmd)

if __name__ == "__main__":
    main()
