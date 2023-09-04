#!/bin/bash
set -e

# Проверить sudo
if [ "$(id -u)" != "0" ]; then
	echo "Please run script as root"
	exit 1
fi

# Set default arguments
author="ton-blockchain"
repo="mytonctrl"
branch="master"
if [[ "$OSTYPE" =~ darwin.* ]]; then
  srcdir="/usr/local/src/"
  bindir="/usr/local/bin/"
else
  srcdir="/usr/src/"
  bindir="/usr/bin/"
fi

# Get arguments
while getopts a:r:b: flag
do
	case "${flag}" in
		a) author=${OPTARG};;
		r) repo=${OPTARG};;
		b) branch=${OPTARG};;
	esac
done

# Цвета
COLOR='\033[92m'
ENDC='\033[0m'

# Установка компонентов python3
pip3 install fastcrc

# Go to work dir
cd ${srcdir}
rm -rf ${srcdir}/${repo}

# Update code
echo "https://github.com/${author}/${repo}.git -> ${branch}"
git clone --recursive https://github.com/${author}/${repo}.git
cd ${repo} && git checkout ${branch} && git submodule update --init --recursive

# migrate old locations for root user
if [ -f "/usr/local/bin/mytoncore/mytoncore.db" ]; then
  echo "Migrating /usr/local/bin/ to $(echo ~root/.local/share/)"

  #wallets
  if [ ! -d "~root/.local/share/mytoncore/wallets/" ]; then
    mkdir -p ~root/.local/share/mytoncore/wallets
  fi
  cd ~root/.local/share/mytoncore/wallets/
  for fn in *; do mv $fn $fn.backup; done
  for fn in /usr/local/bin/mytoncore/wallets/*; do cp $fn $(basename $fn); done

  #pools
  if [ ! -d "~root/.local/share/mytoncore/pools/" ]; then
    mkdir -p ~root/.local/share/mytoncore/pools
  fi
  cd ~root/.local/share/mytoncore/pool/
  for fn in *; do mv $fn $fn.backup; done
  for fn in /usr/local/bin/mytoncore/pool/*; do cp $fn $(basename $fn); done

  #contracts
  if [ ! -d "~root/.local/share/mytoncore/contracts/" ]; then
    mkdir -p ~root/.local/share/mytoncore/contracts
  fi
  cd ~root/.local/share/mytoncore/contracts/
  for fn in *; do mv $fn $fn.backup; done
  for fn in /usr/local/bin/mytoncore/contracts/*; do cp -R $fn $(basename $fn); done
fi

if [[ "$OSTYPE" =~ darwin.* ]]; then
  kickstart -k system/mytoncore
else
  systemctl restart mytoncore
fi

# Конец
echo -e "${COLOR}[1/1]${ENDC} MyTonCtrl components update completed"
exit 0
