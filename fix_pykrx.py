import os

path = r'C:\Users\WIN10\AppData\Local\Programs\Python\Python313\Lib\site-packages\pykrx\website\comm\util.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 잘못된 수정 원래대로 되돌리기
content = content.replace('pass; logger=f"Error occurred', 'print(f"Error occurred')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# 올바른 방식으로 수정 - print 문 전체 줄을 pass로 교체
lines = content.split('\n')
new_lines = []
for line in lines:
    if 'print(f"Error occurred' in line:
        indent = len(line) - len(line.lstrip())
        new_lines.append(' ' * indent + 'pass')
    else:
        new_lines.append(line)

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_lines))

print("완료! 오류 메시지 제거됨")
