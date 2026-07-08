def read_yaml_lines(filepath):
    with open(filepath, 'r',encoding='utf-8') as file:
        lines = file.readlines()
    return [line.strip() for line in lines if line.strip()]
def fileread (name):
    lines = read_yaml_lines(name)
    for i, line in enumerate(lines, 1):
        if "[cursor=pointer]" in line :
            print(f"Line {i}: {line}")
        