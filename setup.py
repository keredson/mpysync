import os

from distutils.core import setup


def long_description():
  readme_fn = os.path.join(os.path.dirname(__file__), 'README.md')
  with open(readme_fn) as f:
    return f.read()

setup(
  name='mpysync',
  version='0.2.0',
  description='Rsync-like tool for MicroPython.',
#  long_description=long_description(),
#  long_description_content_type="text/markdown",
  author='Derek Anderson',
  author_email='public@kered.org',
  url='https://github.com/keredson/mpysync',
  packages=['mpysync'],
  requires=['adafruit_ampy', 'darp', 'requests'],
  classifiers=[
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
    'Operating System :: OS Independent',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
  ],
)


