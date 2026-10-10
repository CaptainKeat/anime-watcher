# Settings interface

Settings groups existing controls into Library, Phone access, Updates, Shortcuts,
and Connections. Each section scrolls independently. The selected section is
remembered while the app is open; changing tabs keeps unsaved form values and
an enabled Phone access session. The main sidebar's update notice stays visible
regardless of the Settings section.

Cards use the existing dark surfaces and purple action color. Heading, description,
field label, control, and action spacing are shared across sections. Labels have
transparent backgrounds, avoiding separate dark strips inside cards. Disabled
actions appear dimmed; fields have a visible focus border. Section tabs show a
purple background and underline when selected and can scroll in a narrow window.

Phone access starts with a compact Sharing off state. Its complete pairing area
is hidden until a server provides a usable link. Sharing on shows a green badge,
QR code on a white surface, labeled Connection and Safari link fields, the pairing
code, and Copy link and Refresh code actions. Failed setup retains the collapsed
form and shows Needs attention plus the actual error. Turning sharing off clears
the link and collapses the area. QR and controls sit side by side at 720 logical
pixels or wider and stack below that width. The firewall action requires sharing
to be active in the packaged Windows app.

Native Qt controls retain keyboard navigation. Labels are associated with their
fields; fields, QR code, and section navigation have accessible names. The native
QR image retains its quiet border. Shortcuts report validation and save results
inline; Reset to defaults changes the form until Save shortcuts applies it.

Network detection, authentication, profile ownership, library transfer safeguards,
backup behavior, and the update pipeline continue to use their existing handlers.
