function scrollToAnchor(iframe, hash) {
    var anchor = get_anchor(iframe.contentWindow.document, hash);
    if (!anchor)
        return;
    var iframe_y = $(iframe).position().top;
    var anchor_y = $(anchor).position().top;
    $(window).scrollTop(iframe_y + anchor_y);
}

function onIFrameLoad(iframe) {
    // place iframe's parent div below navigation
    var nav = $('div#navigation');
    $(iframe).parent().css('top', nav.offset().top + nav.outerHeight());
    // scroll main window to anchor location inside the iframe
    scrollToAnchor(iframe, window.location.hash);
    // copy title
    var title = $(iframe.contentWindow.document).find('title').text();
    if (title) {
        $('title').text(title);
    }
    // fixup links
    var base_url = $(iframe).data('base_url');
    var baseview_url = $(iframe).data('baseview_url');
    var links = $(iframe.contentWindow.document).find('a');
    links.each(function (){
        var link = this;
        link.target = '_top';
        link.href = link.href.replace(base_url, baseview_url);
    });
    // when clicking on a link which is on the same page, we need to scroll to the anchor
    links.click(function (){
        var hash = this.href.substring(this.href.indexOf('#'));
        scrollToAnchor(iframe, hash);
    });
}
