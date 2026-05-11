import secrets
import string

def generate_random_token(length=20):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

random_token = generate_random_token()
with open('/ylstackos/files/token/token', 'w') as tokenfile:
    tokenfile.write(random_token)
print("Random Token:", random_token)
