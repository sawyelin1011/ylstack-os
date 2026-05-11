from rich import print
from rich.text import Text
from rich.console import Console
from rich.markdown import Markdown
import os
import sys
import getpass
from werkzeug.security import generate_password_hash
console = Console()
console.print("Welcome to YL StackOS CLI Tools", style='bold green')
print("This tool can help you manage and maintain your YL StackOS subsystem")
import cmd
sys.path.append('/ylstackos')
from tools import check_password

def login_ylstackcli_shell():
    try:
        while True:
            print("Login to YL StackOS CLI Tools\n")
            password = getpass.getpass("YL StackOS Password: ")
            if check_password(password):
                ylcmd = YLStackCmd()
                ylcmd.cmdloop("Welcome to the YL StackOS CLI Tools")
            if password == '':
                print("please provide a password")
                continue
            else:
                print("Incorrect password (Use the login password of YL StackOS Dashboard)")
        
    except KeyboardInterrupt:
        login_ylstackcli_shell()
    except MemoryError:
        print("MemoryError, retry")
    except Exception as e:
        print(f"Error :{e}")
        login_ylstackcli_shell()

class YLStackCmd(cmd.Cmd):
    prompt = "ylstackos > "

    def do_passwd(self, line):
        """Change Linux User Password"""
        os.system("passwd")

    def do_dashpasswd(self, line):
        """Change YL StackOS Dashboard Login Password"""
        passwd = getpass.getpass("New YL StackOS password: ")
        passwd_check = getpass.getpass("Retype new password: ")
        if passwd != passwd_check:
            print("Password do not match, Please try again")
            print("Password unchanged")
            return True
        hashpwd = generate_password_hash(passwd)
        file_path = '/ylstackos/files/pwd.conf'
        try:
            with open(file_path, 'w') as pwd_file:
                pwd_file.write(hashpwd)
            print("Password changed")
        except Exception as e:
            print(f"Error writing to file: {e}")

    def do_quit(self, line):
        """Exit the application."""
        print("Quit!")
        return True

# Keep legacy alias for backward compat
login_flyoscli_shell = login_ylstackcli_shell

if __name__ == "__main__":
    login_ylstackcli_shell()
