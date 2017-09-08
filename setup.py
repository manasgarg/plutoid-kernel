from setuptools import setup, find_packages

setup(
    name='plutoid_kernel',
    version='0.1.1',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'Click',
    ],
    entry_points='''
        [console_scripts]
        plutoidkernel=plutoid_kernel.scripts.plutoidkernel:main
    ''',
)