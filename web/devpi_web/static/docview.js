function updateIFrame(iframe) {
    var $search = $('#search'), $nav = $('#navigation');
    // create enough space for letting devpi header overlap iframe
    // without hiding iframe content
    $('html', iframe.contentWindow.document).css(
        'margin-top', $search.outerHeight(true) + $nav.outerHeight(true));
}

function onIFrameLoad(iframe) {
    updateIFrame(iframe);
    $(window).resize(function () {
        updateIFrame(iframe);
    });

    // make the devpi header move away on iframe down scrolling
    // and reappear on up scrolling...
    // header consists of search form and nav div,
    // both use {position: relative}
    var $search = $('#search'), $nav = $('#navigation'), headerTop = 0,
        $doc = $(iframe.contentWindow.document), scroll = $doc.scrollTop();

    $doc.scroll(function () {
        var newScroll = $doc.scrollTop();
        // move header along with iframe scrolling...
        headerTop -= newScroll - scroll;
        if (headerTop > 0) {
            // don't move header further down than initial state
            headerTop = 0;
        }
        else {
            // don't move header further up than its height
            //TODO: header still visible because of global offset
            var height = $search.outerHeight(true) + $nav.outerHeight(true);
            if (-headerTop > height) {
                headerTop = -height;
            }
        }
        $search.css('top', headerTop);
        $nav.css('top', headerTop);

        updateIFrame(iframe);
        scroll = newScroll;
    });

    // copy title from iframe's inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
