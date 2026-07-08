def read_yaml_lines(filepath):
    """Read YAML file line by line"""
    with open(filepath, 'r',encoding='utf-8') as file:
        lines = file.readlines()
    return [line.strip() for line in lines if line.strip()]

# Example usage
lines = read_yaml_lines('.playwright-mcp/page-2026-07-07T23-56-39-831Z.yml')
for i, line in enumerate(lines, 1):
    if "[cursor=pointer]" in line :
        print(f"Line {i}: {line}")
    