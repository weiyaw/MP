from setuptools import setup,find_packages
#May need to install Pystan separately with pip
setup(name='pr_copula',
      version='0.1.0',
      description='Martingale Posteriors with Copulas',
      url='http://github.com/edfong/copula',
      author='Edwin Fong',
      author_email='edwin.fong@stats.ox.ac.uk',
      license='BSD 3-Clause',
      packages=find_packages(),
      install_requires=[
          'numpy',
          'scipy',
          'scikit-learn',
          'pandas',
          'matplotlib',
          'seaborn',
          'joblib',
          'tqdm',
          'jax',
          'jaxlib',
          'pydataset',
          'xlrd'
      ],
      include_package_data=True,
      python_requires='>=3.7'
      )
