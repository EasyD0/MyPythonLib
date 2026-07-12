from setuptools import setup, find_packages

setup(
    name="mylib",
    version="0.1.0",
    description="个人Python工具库, 包含Git工具、日志设置和线程池实现",
    author="ace",
    author_email="ace_yuan@outlook.com",
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*"]),
    python_requires=">=3.13",
    install_requires=[],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)