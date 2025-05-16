$(function() {
    $('.help a').click(function() {
        var $help = $('.query_doc.inline');
        // is there a docview iframe?
        var $iframe = $('iframe');
        if ($iframe.length && $help.is(':hidden')) {
            // then hide the iframe's scrollbar
            // (double scrollbar doesn't look nice)
            $('body', $iframe[0].contentWindow.document
              ).css('overflow', 'hidden');
        }
        $help.slideToggle({
            complete: function () {
                if ($iframe.length && $help.is(':hidden')) {
                    // give focus and scrollbar back to iframe
                    var iframeWindow = $iframe[0].contentWindow;
                    iframeWindow.focus();
                    $('body', iframeWindow.document
                      ).css('overflow', 'auto');
                }
            }
        });
        return false;
    });
});
