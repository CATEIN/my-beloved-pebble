// Settings page (rendered by Clay on the phone).
module.exports = [
  {
    type: 'heading',
    defaultValue: 'My Beloved'
  },
  {
    type: 'text',
    defaultValue: 'Flick your wrist to open the locket.'
  },
  {
    type: 'section',
    items: [
      {
        type: 'heading',
        defaultValue: 'Inside the locket'
      },
      {
        type: 'picture-picker',
        messageKey: 'PICTURE',
        label: 'Picture',
        defaultValue: '',
        imageq: require('./vendor/image-q')
      },
      {
        type: 'textarea',
        messageKey: 'MESSAGE',
        label: 'Message',
        description: 'Written in Arial like on makesweet. New lines split it; otherwise it ' +
          'wraps to fit.',
        defaultValue: 'pebble my beloved',
        attributes: {
          maxlength: 80,
          placeholder: 'pebble my beloved'
        }
      },
      {
        type: 'toggle',
        messageKey: 'SWAP_SIDES',
        label: 'Picture on the right',
        description: 'Off: picture in the cover (left), message on the right.',
        defaultValue: false
      },
      {
        type: 'slider',
        messageKey: 'OPEN_SECONDS',
        label: 'Seconds to stay open',
        defaultValue: 3,
        min: 2,
        max: 20,
        step: 1
      }
    ]
  },
  {
    type: 'section',
    items: [
      {
        type: 'heading',
        defaultValue: 'Weather'
      },
      {
        type: 'toggle',
        messageKey: 'USE_CELSIUS',
        label: 'Temperature in Celsius',
        description: 'Off: Fahrenheit.',
        defaultValue: false
      }
    ]
  },
  {
    type: 'submit',
    defaultValue: 'Save'
  },
  {
    type: 'text',
    defaultValue: '<small>The locket is <a href="https://makesweet.com/my/heart-locket">Heart ' +
      'Locket</a> by Paul Fitzpatrick, <a href="https://makesweet.com">makesweet.com</a>. ' +
      'Default picture: <a href="https://commons.wikimedia.org/wiki/File:Pebble_Time_front.jpg">' +
      '"Pebble Time front"</a> by Frmorrison, ' +
      '<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>. ' +
      'Font: Liberation Sans. Dithering: image-q.</small>'
  }
];
