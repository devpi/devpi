function scrollToAnchor(iframe, hash) {
    var anchor = get_anchor(iframe.contentWindow.document, hash);
    if (!anchor)
        return;
    var iframe_y = $(iframe).position().top;
    var anchor_y = $(anchor).position().top;
    $(window).scrollTop(iframe_y + anchor_y);
}

function onIFrameLoad(iframe) {
    // set iframe height to the height of the content, so there are no scrollbars
    iframe.height = $(iframe.contentWindow.document).height() + "px";
    // scroll main window to anchor location inside the iframe
    scrollToAnchor(iframe, window.location.hash);
    // copy title
    var title = $(iframe.contentWindow.document).find('title').text();
    if (title) {
        $('title').text(title);
    }
    // fixup links
    var base_url = $('iframe').data('base_url');
    var baseview_url = $('iframe').data('baseview_url');
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
