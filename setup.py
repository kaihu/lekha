from distutils.core import setup

setup(
    name='Lekha',
    description='A simple PDF viewer',
    version="0.1.1",
    author='Kai Huuhko',
    author_email='kai.huuhko@gmail.com',
    url='http://www.enlightenment.org/',
    keywords="efl enlightenment pdf",
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: X11 Applications',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Other/Nonlisted Topic',
        ],
    packages=['lekha'],
    scripts=['bin/lekha'],
    data_files=[('/usr/share/applications', ['lekha.desktop'])],
    requires=[
        "efl (>=1.13.99)",
        "PyPDF2",
        "xdg",
        ],
)
