#!/usr/bin/env python3
import os
import re
import glob

# Find all Python files that might have union syntax issues
def find_python_files(directory):
    return glob.glob(f"{directory}/**/*.py", recursive=True)

# Fix union syntax in a file
def fix_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    original_content = content

    # Check if file already has typing imports
    has_union = 'Union' in content
    has_list = 'List' in content
    has_dict = 'Dict' in content
    has_tuple = 'Tuple' in content
    has_optional = 'Optional' in content

    # Find existing typing imports
    typing_imports = []
    typing_match = re.search(r'from typing import ([^\n]+)', content)
    if typing_match:
        existing_imports = [imp.strip() for imp in typing_match.group(1).split(',')]
        typing_imports.extend(existing_imports)

    # Add missing imports
    needed_imports = set()
    if re.search(r'\b\w+\s*\|\s*\w+', content):
        needed_imports.add('Union')
    if re.search(r'\b\w+\s*\|\s*None', content):
        needed_imports.add('Optional')
    if re.search(r'\blist\[', content):
        needed_imports.add('List')
    if re.search(r'\bdict\[', content):
        needed_imports.add('Dict')
    if re.search(r'\btuple\[', content):
        needed_imports.add('Tuple')

    # Add missing imports to the list
    for imp in needed_imports:
        if imp not in typing_imports:
            typing_imports.append(imp)

    # Update typing imports if needed
    if typing_match and needed_imports:
        new_imports = ', '.join(sorted(set(typing_imports)))
        content = content.replace(typing_match.group(0), f'from typing import {new_imports}')
    elif needed_imports and not typing_match:
        # Add typing import after other imports
        import_lines = []
        other_lines = []
        in_imports = True
        for line in content.split('\n'):
            if in_imports and (line.startswith('from ') or line.startswith('import ') or line.strip() == ''):
                import_lines.append(line)
            else:
                in_imports = False
                other_lines.append(line)

        new_imports = ', '.join(sorted(needed_imports))
        import_lines.append(f'from typing import {new_imports}')
        content = '\n'.join(import_lines + other_lines)

    # Fix union syntax patterns
    # Type | None -> Optional[Type]
    content = re.sub(r'(\w+)\s*\|\s*None', r'Optional[\1]', content)

    # Type1 | Type2 -> Union[Type1, Type2]
    content = re.sub(r'(\w+)\s*\|\s*(\w+)(?!\s*\])', r'Union[\1, \2]', content)

    # list[Type] -> List[Type]
    content = re.sub(r'\blist\[', 'List[', content)

    # dict[Key, Value] -> Dict[Key, Value]
    content = re.sub(r'\bdict\[', 'Dict[', content)

    # tuple[...] -> Tuple[...]
    content = re.sub(r'\btuple\[', 'Tuple[', content)

    # Only write if content changed
    if content != original_content:
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Fixed: {filepath}")
        return True
    return False

# Main execution
if __name__ == "__main__":
    directory = "/Users/wmobley/Documents/GitHub/upstream/upstream-docker/app"
    files = find_python_files(directory)

    fixed_count = 0
    for filepath in files:
        if fix_file(filepath):
            fixed_count += 1

    print(f"Fixed {fixed_count} files")