function updateIFrame(iframe) {
    // place iframe's parent div below navigation
    var $nav = $('#navigation');
    $(iframe).parent().css('top', $nav.offset().top + $nav.outerHeight(true));
}

function onIFrameLoad(iframe) {
    updateIFrame(iframe);
    $(window).resize(function () {
        updateIFrame(iframe);
    });

    var $doc = $(iframe.contentWindow.document);

    // make the devpi header move away on iframe down scrolling
    // and reappear on up scrolling
    var $search = $('#search'), $nav = $('#navigation'), top = 0,
        oldScroll = $doc.scrollTop();
    // search form and nav div have position: relative
    $search.css('top', top);
    $nav.css('top', top);
    $doc.scroll(function () {
        var scroll = $doc.scrollTop(), diff = scroll - oldScroll;
        top -= diff;
        if (top > 0) {
            // don't move header further down than initial state
            diff += top;
            top = 0;
        }
        else {
            // don't move header further up than its height
            //TODO: still header space left
            var height = $search.outerHeight(true) + $nav.outerHeight(true);
            if (-top > height) {
                diff -= -top - height;
                top = -height;
            }
        }
        // reset iframe scroll if moving header
        scroll -= diff;
        // make sure that iframe is always up-scrollable
        // if devpi header not fully shown
        // by having at least 1px scroll state
        //TODO: better solution (slow header down moving in 1px steps)
        if (top && scroll < 1) {
            scroll = 1;
        }
        $doc.scrollTop(scroll);
        $search.css('top', top);
        $nav.css('top', top);
        updateIFrame(iframe);
        oldScroll = scroll;
    });

    // copy title from inner document
    var title = $doc.find('title').text();
    if (title) {
        $('title').text(title);
    }
}
