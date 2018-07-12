# .bash_profile

alias p="nano ~/.bash_profile; source ~/.bash_profile"

alias log="tail -f /var/log/jupyterhub"
alias conf="n /etc/jupyterhub/jupyterhub_config.py"
alias init="n /etc/init.d/jupyterhub"
#alias boot_script="n /etc/init.d/efs_mount"
alias cron_jupyterhub="n /etc/cron.d/jupyterhub_cron"

#kill and delete ALL containers on this machine
alias drma='d rm -f `d ps -a -q`'
alias dsrma='ds rm -f `ds ps -a -q`'

#the [d] will exclude grep from results
alias psj="ps -ef | grep [j]upyter"

alias log='tail -f /var/log/jupyterhub'

#due to the installation location of pip runtime files (due to either yum or Centos)
#we need to create direct aliases for running key programs in a convenient fashion,
# and we need the extra space after sudo to chain commands correctly
alias sudo="sudo "
alias pip="/usr/local/bin/pip"
alias pip3="/usr/local/bin/pip3"
alias jupyterhub="/usr/local/bin/jupyterhub"

#developer convenience
alias ipy="sudo `which ipython` "
alias sn="sudo nano"
alias v="sudo vim "
alias n="sn"
alias f="cd /etc/jupyterhub"

alias l="ls"
alias ll="ls -hl"
alias lh="ls -hl"
alias lla="ls -hla"

alias u="cd .."
alias uu="u; u"
alias uuu="u; u; u"
# Get the aliases and functions
if [ -f ~/.bashrc ]; then
	. ~/.bashrc
fi

# User specific environment and startup programs

PATH=$PATH:$HOME/.local/bin:$HOME/bin

export PATH


# erases duplicate entries in your bash history
export HISTSIZE=10000000
export HISTFILESIZE=10000000
# append to bash history
shopt -s histappend
# shared bash history between terminals (at prompt append and reread the history file)
export PROMPT_COMMAND="history -a; history -c; history -r; $PROMPT_COMMAND"
