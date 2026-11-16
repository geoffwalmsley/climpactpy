/*
 * The help drawer (#177, components/drawer.html). Each section's ⓘ is a link to its help
 * page; here the link is hidden and the button beside it shown, which opens the drawer
 * with the section's <template>. Not modal: no backdrop and no focus trap. Focus goes to
 * the drawer's title. Escape or the close button closes it and puts focus back on the ⓘ,
 * unless focus has moved on to the page meanwhile.
 */
(function () {
  "use strict";

  var doc = document;
  var opener = null;

  function part(name) {
    return doc.querySelector("[data-drawer" + name + "]");
  }

  function close() {
    var drawer = part("");
    if (!drawer || drawer.hidden) return;
    var active = doc.activeElement;
    var back = !active || active === doc.body || active === opener || drawer.contains(active);
    drawer.hidden = true;
    part("-layout").classList.remove("drawer-layout--open");
    if (opener) {
      opener.setAttribute("aria-expanded", "false");
      if (back && doc.contains(opener)) opener.focus();
    }
    opener = null;
  }

  function open(button) {
    var drawer = part("");
    var template = doc.getElementById(button.getAttribute("data-drawer-open"));
    if (!drawer || !template) return;
    if (opener === button) return close();
    if (opener) opener.setAttribute("aria-expanded", "false");
    part("-title").textContent = template.getAttribute("data-title");
    part("-body").replaceChildren(template.content.cloneNode(true));
    drawer.hidden = false;
    drawer.scrollTop = 0;
    part("-layout").classList.add("drawer-layout--open");
    opener = button;
    button.setAttribute("aria-expanded", "true");
    part("-title").focus();
  }

  function enhance(scope) {
    Array.prototype.forEach.call(scope.querySelectorAll("[data-help-link]"), function (link) {
      link.hidden = true;
      link.nextElementSibling.hidden = false;
    });
  }

  doc.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-drawer-open], [data-drawer-close]");
    if (!button) return;
    if (button.hasAttribute("data-drawer-close")) close();
    else open(button);
  });

  doc.addEventListener("keydown", function (event) {
    /* A modal dialog takes Escape first. */
    if (event.key !== "Escape" || event.defaultPrevented || !opener || doc.querySelector("dialog[open]")) return;
    event.preventDefault();
    close();
  });

  doc.addEventListener("htmx:load", function (event) {
    enhance(event.target);
  });
  enhance(doc);
})();
