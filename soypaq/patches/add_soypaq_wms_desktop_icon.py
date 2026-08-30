from soypaq.install import setup_desktop_icon


def execute():
	"""Legacy patch for sites installed before `after_install` handled this."""
	setup_desktop_icon()
