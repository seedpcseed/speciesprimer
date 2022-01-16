Bootstrap: localimage
From: containers/speciesprimer_base.sif

%environment
PATH="$PATH:/pipeline:/pipeline/gui/daemon:/pipeline/ext-scripts"
BLASTDB="blastdb"
BLAST_USAGE_REPORT=FALSE
FLASK_APP="/pipeline/gui/speciesprimergui.py"
PATH="/pipeline/:${PATH}"

%runscript
exec "$@"

%post
cd / && \
 git clone https://github.com/seedpcseed/speciesprimer
 mv  /speciesprimer/* .

chmod +x /pipeline/*.py
chmod +x /pipeline/gui/daemon/*.py
chmod +x /boot.sh
