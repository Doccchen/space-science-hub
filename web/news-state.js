'use strict';
(() => {
  function mergeItem(previous, patch) {
    if (!previous || !patch || String(previous.id) !== String(patch.id)) return null;
    const next = {...previous};
    for (const [name,value] of Object.entries(patch)) {
      if (value !== undefined && value !== null) next[name] = value;
    }
    // Empty detail metadata is not evidence that a list title/source disappeared.
    for (const name of ['title','source_name','original_url','source_id','published_at','lang']) {
      if (!next[name] && previous[name]) next[name] = previous[name];
    }
    if (next.reading_mode !== 'full_text') next.summary = '';
    return next;
  }
  window.NewsPresentation = {mergeItem};
})();
