import re
with open('ofproto/constants.py', 'r') as f:
    data = f.read()
data = data.replace('    PORT_DESC = 13\n', '    PORT_STATS = 4\n    PORT_DESC = 13\n')
with open('ofproto/constants.py', 'w') as f:
    f.write(data)
