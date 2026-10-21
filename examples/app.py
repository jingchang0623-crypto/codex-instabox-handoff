"""Small host probe for a local -> remote -> local development exercise."""
import json
import os
import platform

MESSAGE = 'Hello from the handoff workspace'

if __name__ == '__main__':
    print(json.dumps({'message': MESSAGE, 'hostname': platform.node(),
                      'system': platform.system(), 'cwd': os.getcwd()}, indent=2))
