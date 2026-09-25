const i=/posm|point[ -]of[ -]sale|display material|merchandis/i;function n(s){return s?s.is_posm!==void 0&&s.is_posm!==null?!!s.is_posm:i.test(s.item_group||""):!1}export{n as i};
