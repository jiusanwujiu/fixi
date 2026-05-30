# Fix prompt_gen.py syntax error - replace problematic line
with open(r'D:\openclaw\workspace\fuxi\src\prompt_gen.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

fixed_lines = []
for line in lines:
    if 'no_advice_format' in line and '禁止' in line:
        fixed_lines.append("    \"no_advice_format\": '''【必须】不得使用“你应该买/卖”或“建议关注”等直接投资建议格式，改为客观分析市场情况。''',\n")
    else:
        fixed_lines.append(line)

with open(r'D:\openclaw\workspace\fuxi\src\prompt_gen.py', 'w', encoding='utf-8') as f:
    f.writelines(fixed_lines)

print('Fixed!')
