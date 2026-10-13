# Serial console reports no size: ash would wrap its echo at 80 columns and split logged commands.
case "$(tty 2>/dev/null)" in
/dev/ttyS*|/dev/console) stty cols 4096 rows 100 2>/dev/null ;;
esac
