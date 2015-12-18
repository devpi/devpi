function onIFrameLoad(iframe) {
    var $body = $('body'),
        $header = $('.header'),
        $doc = $(iframe.contentWindow.document),
        $docHtml = $doc.find('html');

    function update() {
        // create enough space for letting devpi header overlap iframe
        // without hiding iframe content
        $docHtml.css('margin-top', $header.outerHeight(true));
        // make scrollbar visible by adding a margin to the header
        $header.css("margin-right", $body.width() - $doc.width());
    }
    update();
    $(window).resize(update);

    // make devpi header move away on iframe down-scrolling
    // and reappear on up-scrolling...
    $doc.scroll(function () {
        var headerTop = -$doc.scrollTop(),
            headerHeight = $header.outerHeight(true);
        // move header along with iframe scrolling...
        if (headerTop < -headerHeight) {
            // don't move header further down than initial state
            headerTop = -headerHeight;
        }
        $header.css('top', headerTop);
        update();
    });

    // copy title from iframe's inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
