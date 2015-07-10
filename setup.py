
from setuptools import setup, find_packages

from os import path

here = path.abspath(path.dirname(__file__))


with open(path.join(here, 'DESCRIPTION.rst'), encoding='utf-8') as f:
    long_description=f.read()

setup(
    name='pyEnFace',
    version='0.9.6',
    description='A python interface to the Enphase Developer API',
    long_description=long_description,
    url='https://github.com/e2thenegpii/EnphaseInterface',
    author='Eldon Allred',
    author_email='e2thenegpii@gmail.com',
    license='Gnu Public License version 3',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Programming Language :: Python :: 3.4',
        'Topic :: Software Development :: Libraries :: Python Modules',

    ],
    keywords='enphase development',
    packages=find_packages(),
    package_data={'':['DESCRIPTION.rst']},
    include_package_data=True,
    install_requires=['pandas',
        'sqlalchemy',
        'lxml',]
)
