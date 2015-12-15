function updateIFrame(iframe) {
    var $header = $('.header'),
        $doc = $(iframe.contentWindow.document);
    // create enough space for letting devpi header overlap iframe
    // without hiding iframe content
    $('html', iframe.contentWindow.document).css(
        'margin-top', $header.outerHeight(true));
    // make scrollbar visible by adding a margin to the header
    $(".header").css(
        "margin-right", $("body").width() - $doc.width());
}

function onIFrameLoad(iframe) {
    updateIFrame(iframe);
    $(window).resize(function () {
        updateIFrame(iframe);
    });

    // make the devpi header move away on iframe down scrolling
    // and reappear on up scrolling...
    // it uses {position: relative}
    var $header = $('.header'),
        $doc = $(iframe.contentWindow.document);

    $doc.scroll(function () {
        var headerTop = -$doc.scrollTop(),
            headerHeight = $header.outerHeight(true);
        // move header along with iframe scrolling...
        if (headerTop < -headerHeight) {
            // don't move header further down than initial state
            headerTop = -headerHeight;
        }
        $header.css('top', headerTop);
        updateIFrame(iframe);
    });

    // copy title from iframe's inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
