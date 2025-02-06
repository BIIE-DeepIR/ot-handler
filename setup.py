import setuptools

# Read in your README file for the long description
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="ot_handler",  
    version="0.1.0",    
    author="Oskari Vinko",
    author_email="oskari.vinko@immune.engineering",
    description="A comprehensive solution for automating liquid handling tasks on the Opentrons OT-2.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/BIIE-DeepIR/ot-handler",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.10',
)