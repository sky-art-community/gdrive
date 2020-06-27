from setuptools import setup

with open('requirements.txt') as f:
    required = f.read().splitlines()

print(required)

setup(
    name="gdrive",
    version='0.0.1',
    py_modules=['main'],
    install_requires=required,
    entry_points='''
        [console_scripts]
        gdrive=main:gdrive
    ''',
)