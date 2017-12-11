function updateHeaderMargins($header, $body, $doc, $docHtml) {
    // create enough space for letting devpi header overlap iframe
    // without hiding iframe content
    $docHtml.css('margin-top', $header.outerHeight(true));
    // make scrollbar visible by adding a margin to the header
    $header.css("margin-right", $body.width() - $doc.width());
}


function onIFrameLoad(event) {
    var $body = event.data.$body,
        $header = event.data.$header,
        iframe = this,
        $doc = $(iframe.contentWindow.document),
        $docHtml = $doc.find('html');

    // make devpi header move away on iframe down-scrolling
    // and reappear on up-scrolling...
    function scroll() {
        var headerTop = -$doc.scrollTop(),
            headerHeight = $header.outerHeight(true);
        // move header along with iframe scrolling...
        if (headerTop < -headerHeight) {
            // don't move header further down than initial state
            headerTop = -headerHeight;
        }
        $header.css('top', headerTop);
        updateHeaderMargins($header, $body, $doc, $docHtml)
    }

    // initialize header size and position on first load
    scroll();

    // update header position on scroll
    $doc.scroll(scroll);

    // fixup link target, so external links are opened outside the window
    var base_url = $('iframe').data('base_url');
    var $docBase = $doc.find('base');
    if ($docBase.length == 0) {
        var $docHead = $doc.find('head');
        if ($docHead.length == 0) {
            $docHead = $('<head></head>').prependTo($doc);
        }
        $docBase = $('<base>').prependTo($docHead);
    }
    // we add only a target attribute to the base tag, so by default links open
    // outside the iframe
    $docBase.attr('target', '_top');
    // we use the click and submit events to catch stuff added via the dynamic
    // Sphinx search
    $docHtml.on('click', 'a[href]', function(e) {
        var link = this;
        if (link.href.indexOf(base_url) == 0) {
            // let internal links still open inside the iframe
            link.target = '_self';
        }
    });
    $docHtml.on('submit', 'form', function(e) {
        var form = this;
        if (form.action.indexOf(base_url) == 0) {
            // let internal forms still open inside the iframe
            form.target = '_self';
        }
    });

    // copy title from iframe's inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
