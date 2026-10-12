// Clay component: a multi-line text box (Clay only has single-line inputs), styled like
// Clay's input. Line breaks in the message become line breaks in the locket, like on
// makesweet.
module.exports = {
  name: 'textarea',
  template:
    '<div class="component component-textarea">' +
    '  <label class="tap-highlight">' +
    '    <span class="label">{{{label}}}</span>' +
    '    <textarea data-manipulator-target rows="3"' +
    '      {{each key: attributes}}{{key}}="{{this}}"{{/each}}></textarea>' +
    '  </label>' +
    '  {{if description}}<div class="description">{{{description}}}</div>{{/if}}' +
    '</div>',
  style:
    '.section .component-textarea { padding: 0; }' +
    '.component-textarea label { display: block; }' +
    '.component-textarea .label { display: block; padding-bottom: 0.7rem; }' +
    '.component-textarea textarea { display: block; width: 100%; box-sizing: border-box;' +
    '  margin-top: 0.7rem; background: #333333; border-radius: 0.25rem;' +
    '  padding: 0.35rem 0.375rem; border: none; color: #ffffff; font: inherit;' +
    '  resize: vertical; -webkit-appearance: none; appearance: none; }' +
    '.component-textarea textarea::placeholder { color: #858585; }' +
    '.component-textarea textarea:focus { outline: none; }',
  manipulator: 'val',
  defaults: {
    label: '',
    description: '',
    attributes: {}
  }
};
