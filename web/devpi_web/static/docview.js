function scrollToAnchor(iframe, hash) {
    var anchor = get_anchor(iframe.contentWindow.document, hash);
    if (!anchor)
        return;
    var iframe_y = $(iframe).position().top;
    var anchor_y = $(anchor).position().top;
    $(window).scrollTop(iframe_y + anchor_y);
}

function onIFrameLoad(event) {
    var iframe = this,
        $iframe = $(iframe),
        $doc = $(iframe.contentWindow.document),
        $docHtml = $doc.find('html'),
        $docBody = $docHtml.find('body'),
        scrolled_to_anchor = false,
        iframeResizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.contentRect) {
                    const height = Math.ceil(entry.contentRect.height);
                    if (height) {
                        $iframe.height(height);
                        if (!scrolled_to_anchor) {
                            scrollToAnchor(iframe, window.location.hash);
                            scrolled_to_anchor = true;
                        }
                    }
                }
            }
        });

    $docHtml.css('height', 'auto');
    $docHtml.css('overflow-y', 'hidden');
    $docBody.css('height', 'auto');
    $docBody.css('overflow-y', 'hidden');
    // make keyboard actions affect the actual documentation
    // in the iframe by default
    iframe.contentWindow.focus();
    // watch for content size changes to update iframe height
    iframeResizeObserver.observe(iframe.contentWindow.document.body.parentElement);

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
