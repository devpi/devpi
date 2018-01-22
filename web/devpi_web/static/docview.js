function updateHeaderMargins($header, $body, $doc, $docHtml) {
    // create enough space for letting devpi header overlap iframe
    // without hiding iframe content
    $docHtml.css('margin-top', $header.outerHeight(true));
    // make scrollbar visible by adding a margin to the header
    $header.css("margin-right", $body.width() - $doc.width());
}

function scrollToAnchor(iframe, hash) {
    var anchor = get_anchor(iframe.contentWindow.document, hash);
    if (!anchor)
        return;
    var iframe_y = $(iframe).position().top;
    var anchor_y = $(anchor).position().top;
    $(iframe.contentWindow).scrollTop(iframe_y + anchor_y);
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

    scrollToAnchor(iframe, window.location.hash);

    // initialize header size and position on first load
    scroll();

    // update header position on scroll
    $doc.scroll(scroll);

    // fixup link target, so external links are opened outside the window
    var base_url = $('iframe').data('base_url');
    var baseview_url = $(iframe).data('baseview_url');
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
            // scroll to anchor in case it is on the same page
            var idx = link.href.indexOf('#');
            if (idx != -1) {
                var hash = link.href.substring(idx);
                scrollToAnchor(iframe, hash);
            }
            // rewrite internal links to update browser url
            // rather than stay into iframe
            link.href = link.href.replace(base_url, baseview_url);
        };
        if (link.href.indexOf(baseview_url) == 0) {
            // scroll to anchor in case it is on the same page
            // do it also for baseview_url when the user navigates a lot
            // on the same page
            var idx = link.href.indexOf('#');
            if (idx != -1) {
                var hash = link.href.substring(idx);
                scrollToAnchor(iframe, hash);
            }
        }
    });
    $docHtml.on('submit', 'form', function(e) {
        var form = this;
        if (form.action.indexOf(base_url) == 0) {
            // rewrite internal forms to update browser url
            // rather than stay into iframe
            form.action = form.action.replace(base_url, baseview_url);
        }
    });

    // copy title from iframe's inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
