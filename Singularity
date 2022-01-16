Bootstrap: docker
From: ubuntu:20.04

%environment
LANG=en_US.UTF-8
LC_ALL=en_US.UTF-8
PATH="/opt/miniconda/envs/env/bin:/opt/miniconda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/R-4.1.2/bin:$PATH"
PATH="$PATH:/programs:/pipeline:/pipeline/gui/daemon:/pipeline/ext-scripts"
BLASTDB="/blastdb"
BLAST_USAGE_REPORT=FALSE
FLASK_APP="/pipeline/gui/speciesprimergui.py"
PATH="/pipeline/:${PATH}"

%runscript
exec "$@"

%post
TZ=Europe/Zurich
ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

apt-get update && apt-get install -y \
 apt-utils \
 nano \
 texlive-font-utils \
 curl \
 unzip \
 parallel \
 build-essential \
 gfortran \
 git \
 wget \
 python3-pip \
 python3-wget \
 python3-daemon \
 && apt-get clean

mkdir -p /usr/share/man/man1/
apt-get install -y -f default-jdk default-jre

mkdir /programs && mkdir /primerdesign && mkdir /blastdb && mkdir /programs/tmp

cd / && \
 git clone https://github.com/seedpcseed/speciesprimer
 mv  /speciesprimer/* .

ac_cv_func_malloc_0_nonnull=yes

cd /programs && wget -nv \
 https://github.com/libgd/libgd/releases/download/gd-2.2.5/libgd-2.2.5.tar.gz \
 && tar xf libgd-2.2.5.tar.gz && cd libgd-2.2.5 && ./configure && make && make install \
 && echo "/usr/local/lib" >> /etc/ld.so.conf && ldconfig

cd /programs && wget -nv \
 http://www.unafold.org/download/mfold-3.6.tar.gz \
 && tar xf mfold-3.6.tar.gz \
 && cd mfold-3.6 && ./configure && make && make install

cd /programs && wget -nv \
 https://github.com/mthenw/frontail/releases/download/v4.8.0/frontail-linux \
 && chmod +x frontail-linux

cd /programs && git clone https://github.com/biologger/MFEprimer-py3.git \
 && cd MFEprimer-py3 && python3 setup.py install && python3 setup.py install_data

cd /programs && rm *.tar.gz

enc2xs -C

export PATH="/opt/miniconda/bin:$PATH"
   echo "Downloading Miniconda installer ..."
   conda_installer="/miniconda.sh"
   wget https://repo.anaconda.com/miniconda/Miniconda3-4.6.14-Linux-x86_64.sh -O /miniconda.sh
   #curl -fsSL --retry 5 -o "$conda_installer" https://repo.continuum.io/miniconda/Miniconda3-4.6.14-Linux-x86_64.sh
   bash "$conda_installer" -b -p /opt/miniconda
   rm -f "$conda_installer"
conda config --system --prepend channels conda-forge
conda config --system --set auto_update_conda false
conda config --system --set show_channel_urls true
conda config --add channels bioconda
conda config --add channels anaconda
conda config --add channels biocore
conda update conda
sync && conda clean -y --all && sync

conda install -y mamba
mamba install -y \
 blast \
 tbl2asn \
 mafft \
 prank \
 roary \
 prokka \
 primer3 \
 fasttree \
 emboss \
 biopython \
 numpy \
 flask \
 flask-wtf \
 gunicorn \
 pytest \
 pytest-cov \
 codecov \
 pyani \
 psutil \
 ncbi-genome-download \
 pywget

chmod +x /pipeline/*.py
chmod +x /pipeline/gui/daemon/*.py
chmod +x /boot.sh
