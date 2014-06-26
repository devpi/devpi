function get_anchor(document, hash) {
    hash = hash.replace('#', '')
    if (hash === "") {
        return;
    }
    var anchor = document.getElementById(hash);
    if (anchor === null) {
        var selector = 'a[name="' + hash + '"]';
        anchor = $(document).find(selector);
        if (!anchor.length) {
            return;
        }
        return anchor[0];
    }
    return anchor;
}

$(function() {
    var anchor = get_anchor(document, window.location.hash);
    if (anchor !== null) {
        anchor = $(anchor).parent('.toxresult');
        if (anchor.length) {
            anchor = anchor[0]
        } else {
            anchor = null;
        }
    }
    $('.toxresult.passed').each(function() {
        if (this === anchor) {
            $(this).addClass('opened');
        } else {
            $(this).addClass('closed');
        }
    });
    $('.toxresult.failed').addClass('opened');
    $('.toxresult h2').click(function () {
        $(this).parent().toggleClass('closed opened');
    });
});
